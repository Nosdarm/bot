import asyncio
import discord
from discord.ext import commands # Import commands
import threading
from fastapi import FastAPI
from app.config import logger # Import the configured logger
from app.db import init_db, SessionLocal, transactional_session # Import transactional_session
from app.models import GuildConfig, Player, Location, Party # Import Party model
from app import crud # Import crud module
from app.rules_engine import load_rules_config as init_guild_rules # alias for RuleConfig initialization
from app.world_state_manager import load_world_state as init_guild_world_state # Alias for WorldState initialization
from app.locations_manager import get_location_by_static_id # For !start command
from app import party_manager # Import party_manager
from app.actions_logic import handle_move_action # For !move command
# get_player_by_discord_id is in crud.
# player_manager might be needed if specific player functions beyond crud are used. For now, crud is primary.

# 1. Define Intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True # Crucial for prefix commands to read message content

# 2. Create Discord Bot instance
# Changed from discord.Client to commands.Bot
bot = commands.Bot(command_prefix="!", intents=intents)
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE" # Replace with your actual bot token

# 3. Define Event Handlers using the 'bot' instance
@bot.event
async def on_ready():
    logger.info(f"Discord bot logged in as {bot.user}") # Use bot.user
    logger.info("Bot is ready and listening for commands.")

# on_message is still useful for logging or non-command interactions
# but commands will be handled by their decorators.
# The bot will also process commands from messages, so ensure this doesn't interfere.
# For prefix commands, the bot automatically handles messages that start with the prefix.
# You might not need a custom on_message if all you do is commands and logging them.
# However, if you want to log *all* messages including command attempts:
@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user: # Use bot.user
        return
    guild_name = message.guild.name if message.guild else "DM"
    # Log message, but also ensure commands are processed
    logger.info(f"Message from {message.author} in {guild_name}: {message.content}")
    # Process commands explicitly if you override on_message in certain ways,
    # but for simple logging like this, it's often fine.
    # If commands stop working, you might need: await bot.process_commands(message)
    # However, typically, just defining this event handler for logging alongside commands is okay.


@bot.event
async def on_guild_join(guild: discord.Guild):
    logger.info(f"Bot joined guild: {guild.name} (ID: {guild.id})")

    # Create GuildConfig using transactional_session and crud operations
    try:
        with transactional_session(guild_id=guild.id) as db:
            # Use a specific getter if available, or direct query.
            # Assuming crud.get_guild_config_by_guild_id was added to crud.py
            existing_config = crud.get_guild_config_by_guild_id(db, guild_id=guild.id)
            if not existing_config:
                guild_config_data = {"guild_id": guild.id, "bot_language": "en"}
                # guild_id is part of data for create_entity, no need for separate guild_id param here
                crud.create_entity(db, GuildConfig, guild_config_data)
                logger.info(f"Created GuildConfig for guild {guild.id}")
            else:
                logger.info(f"GuildConfig already exists for guild {guild.id}. Language: {existing_config.bot_language}")
    except Exception as e:
        logger.error(f"Error ensuring GuildConfig for {guild.id}: {e}", exc_info=True)
        # Decide if bot should leave guild or operate with potential issues
        # For now, just log and continue to RuleConfig initialization

    # Initialize RuleConfig (this will use its own transaction via load_rules_config)
    try:
        logger.info(f"Initializing RuleConfig for guild {guild.id}...")
        init_guild_rules(guild.id) # This will create and cache if not exists
        logger.info(f"RuleConfig initialized for guild {guild.id}")
    except Exception as e:
        logger.error(f"Error initializing RuleConfig for {guild.id}: {e}", exc_info=True)

    # Initialize WorldState (this will use its own transaction via load_world_state)
    try:
        logger.info(f"Initializing WorldState for guild {guild.id}...")
        init_guild_world_state(guild.id) # This will create and cache if not exists
        logger.info(f"WorldState initialized for guild {guild.id}")
    except Exception as e:
        logger.error(f"Error initializing WorldState for {guild.id}: {e}", exc_info=True)

    # Define and ensure default starting location
    # This constant is used by on_guild_join and potentially !start if player needs to be reset to a known loc
    # DEFAULT_STARTING_LOCATION_STATIC_ID is defined below, before !start command
    DEFAULT_STARTING_LOCATION = {
        "static_id": "starting_crossroads",
        "name_i18n": {"en": "Starting Crossroads", "ru": "Начальный Перекресток"},
        "descriptions_i18n": {
            "en": "A dusty crossroads. Paths lead north, south, east, and west.",
            "ru": "Пыльный перекресток. Дороги ведут на север, юг, восток и запад."
        },
        "type": "crossroads",
        "neighbor_locations_json": {
             "town_square_static_id": {"en": "a well-worn path", "ru": "протоптанная тропа"},
             "dark_forest_entrance_static_id": {"en": "an overgrown trail", "ru": "заросшая тропа"}
        }
        # coordinates_json can be omitted to use default None
    }

    try:
        logger.info(f"Ensuring default starting location for guild {guild.id}...")
        with transactional_session(guild_id=guild.id) as db:
            # Check if the location already exists using its static_id for the guild
            existing_loc = db.query(Location).filter(
                Location.guild_id == guild.id,
                Location.static_id == DEFAULT_STARTING_LOCATION["static_id"]
            ).first()

            if not existing_loc:
                loc_data = DEFAULT_STARTING_LOCATION.copy()
                # guild_id is passed as a separate parameter to crud.create_entity
                # if it's not part of the main data dictionary, or if the model requires it.
                # The crud.create_entity I defined earlier handles adding guild_id if passed as a param.
                crud.create_entity(db, Location, loc_data, guild_id=guild.id)
                logger.info(f"Created default starting location '{DEFAULT_STARTING_LOCATION['static_id']}' for guild {guild.id}")
            else:
                logger.info(f"Default starting location '{DEFAULT_STARTING_LOCATION['static_id']}' already exists for guild {guild.id}")
    except Exception as e:
        logger.error(f"Error ensuring default starting location for guild {guild.id}: {e}", exc_info=True)

@bot.event
async def on_guild_remove(guild: discord.Guild):
    logger.info(f"Bot removed from guild: {guild.name} (ID: {guild.id}). No data deleted at this time.")

# 4. Implement Commands

# Static ID for the default starting location, used by !start and on_guild_join
DEFAULT_STARTING_LOCATION_STATIC_ID = "starting_crossroads"

@bot.command(name='ping')
async def ping(ctx: commands.Context):
    logger.info(f"!ping command invoked by {ctx.author} in guild {ctx.guild.id if ctx.guild else 'DM'}.")
    await ctx.send('Pong!')

@bot.command(name='lang')
async def lang(ctx: commands.Context, language: str = None):
    if not language:
        await ctx.send("Please specify a language. Usage: `!lang [ru|en]`")
        return

    if language.lower() not in ['ru', 'en']:
        await ctx.send("Invalid language. Please choose 'ru' or 'en'.")
        return

    try:
        with transactional_session(guild_id=ctx.guild.id) as db:
            player = crud.get_player_by_discord_id(db, guild_id=ctx.guild.id, discord_id=ctx.author.id)

            if not player:
                player_data = {
                    "discord_id": ctx.author.id,
                    # guild_id will be added by create_entity
                    "selected_language": language.lower()
                }
                player = crud.create_entity(db, Player, player_data, guild_id=ctx.guild.id)
                await ctx.send(f"Welcome! Your language is set to {language.lower()}.")
                logger.info(f"New player {ctx.author.id} in guild {ctx.guild.id} created and language set to {language.lower()}.")
            else:
                player = crud.update_entity(db, player, {"selected_language": language.lower()})
                await ctx.send(f"Your language has been updated to {language.lower()}.")
                logger.info(f"Player {ctx.author.id} in guild {ctx.guild.id} updated language to {language.lower()}.")
        # Commit and session close are handled by transactional_session
    except Exception as e:
        # No db.rollback() needed here, transactional_session handles it
        logger.error(f"Error in !lang command for player {ctx.author.id} in guild {ctx.guild.id}: {e}", exc_info=True)
        await ctx.send("An error occurred while setting your language.")

@bot.command(name='set_bot_language')
@commands.has_permissions(administrator=True)
async def set_bot_language(ctx: commands.Context, language: str = None):
    if not language:
        await ctx.send("Please specify a language. Usage: `!set_bot_language [ru|en]`")
        return

    if language.lower() not in ['ru', 'en']:
        await ctx.send("Invalid language. Please choose 'ru' or 'en'.")
        return

    db = SessionLocal()
    try:
        guild_config = db.query(GuildConfig).filter(GuildConfig.guild_id == ctx.guild.id).first()
        if not guild_config:
            guild_config = GuildConfig(guild_id=ctx.guild.id, bot_language=language.lower())
            db.add(guild_config)
            logger.warning(f"GuildConfig created on demand for guild {ctx.guild.id} during set_bot_language.")
        else:
            guild_config.bot_language = language.lower()

        db.commit()
        await ctx.send(f"Bot language for this server has been set to {language.lower()}.")
        logger.info(f"Bot language for guild {ctx.guild.id} set to {language.lower()} by {ctx.author.id}.")
    except Exception as e:
        db.rollback()
        logger.error(f"Error setting bot language for guild {ctx.guild.id}: {e}", exc_info=True)
        await ctx.send("An error occurred while setting the bot language.")
    finally:
        db.close()

@set_bot_language.error
async def set_bot_language_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission to use this command.")
        logger.warning(f"User {ctx.author} (ID: {ctx.author.id}) attempted to use !set_bot_language without permissions in guild {ctx.guild.id}.")
    elif isinstance(error, commands.CommandInvokeError) and isinstance(error.original, discord.Forbidden):
        await ctx.send("I don't have permission to send messages here or perform this action.")
        logger.error(f"Discord API permission error in set_bot_language: {error.original}", exc_info=True)
    else:
        logger.error(f"Error in set_bot_language command: {error}", exc_info=True)
        await ctx.send("An unexpected error occurred. Please check the logs.")

@bot.command(name='start')
async def start_game(ctx: commands.Context):
    guild_id = ctx.guild.id
    discord_id = ctx.author.id

    logger.info(f"Player {discord_id} in guild {guild_id} initiated !start command.")

    try:
        with transactional_session(guild_id=guild_id) as db:
            # Check if GuildConfig exists
            guild_config = crud.get_guild_config_by_guild_id(db, guild_id=guild_id)
            if not guild_config:
                logger.error(f"Critical: GuildConfig not found for guild {guild_id} during !start. Bot might not have been properly added.")
                await ctx.send("Error: Server configuration not found. Please try re-adding the bot or contact an admin.")
                return

            # Check if player already exists
            existing_player = crud.get_player_by_discord_id(db, guild_id=guild_id, discord_id=discord_id)
            if existing_player:
                logger.info(f"Player {discord_id} in guild {guild_id} already exists (ID: {existing_player.id}).")
                await ctx.send("You have already started your adventure in this guild!")
                return

            # Get the default starting location
            starting_location = get_location_by_static_id(db, guild_id=guild_id, static_id=DEFAULT_STARTING_LOCATION_STATIC_ID)
            if not starting_location:
                logger.error(f"Default starting location '{DEFAULT_STARTING_LOCATION_STATIC_ID}' not found for guild {guild_id}.")
                await ctx.send("Error: Default starting location not found for this server. Please contact an admin.")
                return

            # Create new player
            player_data = {
                "discord_id": discord_id,
                "guild_id": guild_id, # Ensure guild_id is part of the data for create_entity
                "selected_language": guild_config.bot_language, # Default to guild's language
                "current_location_id": starting_location.id,
                "xp": 0,
                "level": 1,
                "unspent_xp": 0,
                "gold": 0,
                "current_status": "active",
                "collected_actions_json": {} # Initialize with empty JSON
            }

            # create_entity is designed to handle guild_id if it's a key in player_data,
            # or if passed as a separate guild_id parameter (which it is not here, so it must be in player_data).
            new_player = crud.create_entity(db, Player, player_data)

            if new_player:
                logger.info(f"New player {new_player.discord_id} (DB ID: {new_player.id}) created in guild {guild_id} at location {starting_location.id}.")
                # Use get_localized_text for the location name if available, or fallback
                # For now, direct access for simplicity as get_localized_text is not directly imported here.
                location_name = starting_location.name_i18n.get(guild_config.bot_language, starting_location.name_i18n.get('en', DEFAULT_STARTING_LOCATION_STATIC_ID))
                await ctx.send(f"Welcome, {ctx.author.mention}! Your adventure begins at '{location_name}'. Your language is {guild_config.bot_language}.")
            else:
                # This case should ideally be caught by exceptions in create_entity or transactional_session
                logger.error(f"Failed to create player {discord_id} in guild {guild_id} (crud.create_entity returned None).")
                await ctx.send("An unexpected error occurred while creating your character. Please try again.")
    except Exception as e:
        logger.error(f"Exception in !start command for player {discord_id} in guild {guild_id}: {e}", exc_info=True)
        await ctx.send("A critical error occurred. Please contact an administrator or try again later.")


@bot.group(name='party', invoke_without_command=True)
async def party(ctx: commands.Context):
    # Send help text if !party is called without a subcommand
    help_text = "Party commands:\n"
    help_text += "`!party create <name>` - Creates a new party with you as the leader.\n"
    help_text += "`!party leave` - Leaves your current party. If you are the leader, the party is disbanded.\n"
    help_text += "`!party disband` - Disbands your current party (leader only).\n"
    # Add more subcommands to help_text as they are implemented (e.g., invite, kick, members)
    await ctx.send(help_text)

@party.command(name='create')
async def party_create(ctx: commands.Context, *, party_name: str = None):
    if not party_name:
        await ctx.send("Please provide a name for your party. Usage: `!party create <name>`")
        return

    guild_id = ctx.guild.id
    discord_id = ctx.author.id
    logger.info(f"User {discord_id} in guild {guild_id} trying to create party: {party_name}")

    try:
        with transactional_session(guild_id=guild_id) as db:
            player = crud.get_player_by_discord_id(db, guild_id=guild_id, discord_id=discord_id) # Use crud
            if not player:
                await ctx.send("You need to have started the game first (`!start`).")
                return

            if player.current_party_id:
                existing_party = party_manager.get_party_by_id(db, player.current_party_id)
                await ctx.send(f"You are already in a party ('{existing_party.name if existing_party else 'Unknown'}'). Leave it first to create a new one.")
                return

            if party_manager.get_party_by_name(db, guild_id, party_name):
                await ctx.send(f"A party with the name '{party_name}' already exists in this guild.")
                return

            party_data = {
                "guild_id": guild_id,
                "name": party_name,
                "leader_id": player.id,
                "player_ids_json": [player.id],
                "current_location_id": player.current_location_id,
                "turn_status": "pending_actions"
            }
            new_party = crud.create_entity(db, Party, party_data)

            if new_party:
                player.current_party_id = new_party.id
                # db.add(player) # Session tracks changes to 'player' if it's already persistent and modified.
                               # If player was newly created in same transaction and not merged, add might be needed.
                               # For an existing player, direct assignment is usually enough.
                logger.info(f"Party '{new_party.name}' (ID: {new_party.id}) created by Player ID {player.id} in guild {guild_id}.")
                await ctx.send(f"Party '{new_party.name}' created! You are the leader.")
            else:
                logger.error(f"Failed to create party '{party_name}' for player {discord_id} in guild {guild_id}.")
                await ctx.send("Error creating party. Please try again.")
    except Exception as e:
        logger.error(f"Exception in !party create for player {discord_id} in guild {guild_id}: {e}", exc_info=True)
        await ctx.send("A critical error occurred while creating the party.")

@party.command(name='leave')
async def party_leave(ctx: commands.Context):
    guild_id = ctx.guild.id
    discord_id = ctx.author.id
    logger.info(f"User {discord_id} in guild {guild_id} trying to leave party.")

    try:
        with transactional_session(guild_id=guild_id) as db:
            player = crud.get_player_by_discord_id(db, guild_id=guild_id, discord_id=discord_id)
            if not player or not player.current_party_id:
                await ctx.send("You are not currently in a party.")
                return

            party_to_leave = party_manager.get_party_by_id(db, player.current_party_id)
            if not party_to_leave:
                logger.warning(f"Player {player.id} had current_party_id {player.current_party_id} but party not found. Clearing.")
                player.current_party_id = None
                # db.add(player) # As above, session tracks if player is persistent.
                await ctx.send("You were in an invalid party. It has been cleared. You are not in a party now.")
                return

            original_party_name = party_to_leave.name

            if party_to_leave.leader_id == player.id:
                logger.info(f"Leader (Player ID: {player.id}) is leaving party '{original_party_name}'. Disbanding.")
                other_players_in_party = db.query(Player).filter(
                    Player.guild_id == guild_id, # Ensure same guild
                    Player.current_party_id == party_to_leave.id,
                    Player.id != player.id # Don't modify the leader again here
                ).all()
                for p_in_party in other_players_in_party:
                    p_in_party.current_party_id = None

                player.current_party_id = None # Leader also leaves
                crud.delete_entity(db, party_to_leave)
                await ctx.send(f"You have left and disbanded the party '{original_party_name}'.")
            else:
                # Member leaves
                if party_to_leave.player_ids_json and player.id in party_to_leave.player_ids_json:
                    new_player_ids = [pid for pid in party_to_leave.player_ids_json if pid != player.id]
                    party_to_leave.player_ids_json = new_player_ids # Reassign for SQLAlchemy to detect change

                player.current_party_id = None
                logger.info(f"Player {player.id} left party '{original_party_name}'. New members: {party_to_leave.player_ids_json}")
                await ctx.send(f"You have left the party '{original_party_name}'.")
    except Exception as e:
        logger.error(f"Exception in !party leave for player {discord_id} in guild {guild_id}: {e}", exc_info=True)
        await ctx.send("A critical error occurred while leaving the party.")

@party.command(name='disband')
@commands.has_permissions(administrator=False) # Example: check if it's the leader, not just admin
async def party_disband(ctx: commands.Context):
    guild_id = ctx.guild.id
    discord_id = ctx.author.id
    logger.info(f"User {discord_id} in guild {guild_id} trying to disband party.")

    try:
        with transactional_session(guild_id=guild_id) as db:
            player = crud.get_player_by_discord_id(db, guild_id=guild_id, discord_id=discord_id)
            if not player or not player.current_party_id:
                await ctx.send("You are not currently in a party.")
                return

            party_to_disband = party_manager.get_party_by_id(db, player.current_party_id)
            if not party_to_disband:
                logger.warning(f"Player {player.id} had current_party_id {player.current_party_id} but party not found for disband. Clearing.")
                player.current_party_id = None
                await ctx.send("You were in an invalid party. It has been cleared.")
                return

            if party_to_disband.leader_id != player.id:
                await ctx.send("Only the party leader can disband the party.")
                return

            original_party_name = party_to_disband.name
            logger.info(f"Leader (Player ID: {player.id}) is disbanding party '{original_party_name}'.")

            players_in_party = db.query(Player).filter(
                Player.guild_id == guild_id, # Ensure same guild
                Player.current_party_id == party_to_disband.id
            ).all()
            for p_in_party in players_in_party:
                p_in_party.current_party_id = None

            crud.delete_entity(db, party_to_disband)
            await ctx.send(f"Party '{original_party_name}' has been disbanded by the leader.")
    except Exception as e:
        logger.error(f"Exception in !party disband for player {discord_id} in guild {guild_id}: {e}", exc_info=True)
        await ctx.send("A critical error occurred while disbanding the party.")

@bot.command(name='move')
async def move_command(ctx: commands.Context, *, target_location_identifier: str = None):
    if not target_location_identifier:
        await ctx.send("Where would you like to move? Usage: `!move <location_static_id>`")
        return

    guild_id = ctx.guild.id
    discord_id = ctx.author.id

    logger.info(f"Player {discord_id} in guild {guild_id} trying to move to '{target_location_identifier}'.")

    try:
        with transactional_session(guild_id=guild_id) as db:
            # Fetch player using discord_id and guild_id first
            player = crud.get_player_by_discord_id(db, guild_id=guild_id, discord_id=discord_id)
            if not player:
                await ctx.send("You need to have started the game first (`!start`).")
                return

            if not player.id: # Should ideally not happen if player is fetched correctly and has an ID
                logger.error(f"Player object for discord_id {discord_id} in guild {guild_id} is missing a primary key ID.")
                await ctx.send("Error: Your player record is invalid. Please contact an administrator.")
                return

            # handle_move_action expects the player's primary key (player.id)
            status, message = handle_move_action(db, guild_id, player.id, target_location_identifier)

            if status == 'success':
                await ctx.send(message)
            else:
                # Prepend "Move failed: " only if not already part of the message from actions_logic
                error_prefix = "Move failed: "
                if message.lower().startswith(error_prefix.lower()):
                    await ctx.send(message)
                else:
                    await ctx.send(f"{error_prefix}{message}")
    except Exception as e:
        logger.error(f"Critical error in !move command for player {discord_id} to '{target_location_identifier}': {e}", exc_info=True)
        await ctx.send("A critical error occurred while trying to move. Please contact an administrator.")

# FastAPI app instance
app = FastAPI()
discord_thread = None

def run_discord_bot_sync(): # Renamed to avoid confusion if we had an async run_discord_bot
    try:
        # Updated BOT_TOKEN check
        if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
            logger.error("BOT_TOKEN is not configured. Please set it in app/main.py or as an environment variable. Discord bot will not start.")
            return
        logger.info("Starting Discord bot in a separate thread...")
        bot.run(BOT_TOKEN) # Use bot.run
    except Exception as e:
        logger.error(f"Error in Discord bot thread: {e}", exc_info=True)

@app.on_event("startup")
async def on_startup():
    logger.info("FastAPI application startup commencing...")
    # logger.info("Initializing database...")
    # init_db() # Database creation is now handled by Alembic migrations.
    logger.info("Database initialization (init_db) is commented out. Run Alembic migrations manually.")
    logger.info("Attempting to start Discord bot thread...")
    global discord_thread
    discord_thread = threading.Thread(target=run_discord_bot_sync, daemon=True)
    discord_thread.start()
    logger.info("Discord bot thread initiation sequence complete.")

@app.get("/")
async def root():
    return {"message": "Hello World - Text RPG Bot Backend with Discord Commands"}

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("FastAPI app shutting down. Initiating Discord bot closure...")
    try:
        if bot.is_ready(): # Use bot.is_ready()
             await bot.close() # Use bot.close()
             logger.info("Discord bot successfully closed.")
        else:
            logger.info("Discord bot was not running or already closed.")
    except Exception as e:
        logger.error("Error during Discord bot closure.", exc_info=True)
