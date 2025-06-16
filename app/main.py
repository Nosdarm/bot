import asyncio
import discord
from discord.ext import commands # Import commands
import threading
from fastapi import FastAPI
from app.config import logger # Import the configured logger
from app.db import init_db, SessionLocal, transactional_session # Import transactional_session
from app.models import GuildConfig, Player # Import GuildConfig and Player models
from app import crud # Import crud module
from app.rules_engine import load_rules_config as init_guild_rules # alias for RuleConfig initialization

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

@bot.event
async def on_guild_remove(guild: discord.Guild):
    logger.info(f"Bot removed from guild: {guild.name} (ID: {guild.id}). No data deleted at this time.")

# 4. Implement Commands
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
