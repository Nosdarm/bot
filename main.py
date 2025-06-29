import discord
from discord.ext import commands
import logging
from bot.game.game_manager import GameManager
from bot.services.db_service import DBService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot setup
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)
db_service = DBService()
game_manager = GameManager(db_service, {})

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    logger.info(f'Guilds: {[guild.name for guild in bot.guilds]}')
    for guild in bot.guilds:
        await game_manager.location_manager.load_locations_for_guild(guild.id)

from bot.game.guild_initializer import initialize_guild_data

@bot.event
async def on_guild_join(guild):
    logger.info(f'Joined new guild: {guild.name} (id: {guild.id})')
    await initialize_guild_data(guild)
    await game_manager.location_manager.load_locations_for_guild(guild.id)

@bot.event
async def on_guild_remove(guild):
    logger.info(f'Removed from guild: {guild.name} (id: {guild.id})')

@bot.command(name='ping')
async def ping(ctx):
    await ctx.send('Pong!')

@bot.command(name='start')
async def start(ctx):
    await game_manager.character_manager.create_character(ctx.guild.id, ctx.author.id, ctx.author.name)
    await ctx.send("Welcome to the world!")

@bot.group(name='party')
async def party(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Invalid party command passed...')

@party.command(name='create')
async def create_party(ctx, name: str):
    await game_manager.character_manager.create_party(ctx.guild.id, ctx.author.id, name)
    await ctx.send(f"Party '{name}' created!")

@party.command(name='join')
async def join_party(ctx, party_id: int):
    await game_manager.character_manager.join_party(ctx.guild.id, ctx.author.id, party_id)
    await ctx.send(f"Joined party!")

@party.command(name='leave')
async def leave_party(ctx):
    await game_manager.character_manager.leave_party(ctx.guild.id, ctx.author.id)
    await ctx.send(f"Left party.")

@party.command(name='disband')
async def disband_party(ctx):
    await game_manager.character_manager.disband_party(ctx.guild.id, ctx.author.id)
    await ctx.send(f"Party disbanded.")

@bot.command(name='move')
async def move(ctx, destination: str):
    await game_manager.character_manager.add_action_to_queue(ctx.guild.id, ctx.author.id, "MOVE", {"destination": destination})
    await game_manager.game_log_manager.log_event(
        guild_id=ctx.guild.id,
        event_type="PLAYER_ACTION",
        details={"player_id": ctx.author.id, "action_type": "MOVE", "action_data": {"destination": destination}}
    )
    await ctx.send(f"Action 'move {destination}' added to your queue. Use /end_turn to process it.")

@bot.command(name='look')
async def look(ctx):
    await game_manager.character_manager.add_action_to_queue(ctx.guild.id, ctx.author.id, "LOOK", {})
    await game_manager.game_log_manager.log_event(
        guild_id=ctx.guild.id,
        event_type="PLAYER_ACTION",
        details={"player_id": ctx.author.id, "action_type": "LOOK", "action_data": {}}
    )
    await ctx.send("Action 'look' added to your queue. Use /end_turn to process it.")

@bot.command(name='end_turn')
async def end_turn(ctx):
    await ctx.send("Ending turn and processing actions...")
    await game_manager.turn_processing_service.process_player_turns(ctx.guild.id)
    await game_manager.turn_processing_service.process_guild_turn(ctx.guild.id, {})
    await ctx.send("Turn processing complete.")

@bot.command(name='interact')
async def interact(ctx, *, target: str):
    await game_manager.character_manager.add_action_to_queue(ctx.guild.id, ctx.author.id, "INTERACT", {"target": target})
    await game_manager.game_log_manager.log_event(
        guild_id=ctx.guild.id,
        event_type="PLAYER_ACTION",
        details={"player_id": ctx.author.id, "action_type": "INTERACT", "action_data": {"target": target}}
    )
    await ctx.send(f"Action 'interact with {target}' added to your queue. Use /end_turn to process it.")

@bot.command(name='levelup')
async def levelup(ctx, attribute: str):
    result = await game_manager.submit_player_action(ctx.guild.id, ctx.author.id, "LEVELUP", {"attribute": attribute})
    await ctx.send(result['message'])

@bot.group(name='master')
@commands.has_permissions(administrator=True)
async def master(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Invalid master command passed...')

@master.command(name='resolve_conflict')
async def resolve_conflict(ctx, conflict_id: int, outcome: str):
    # ...
    await ctx.send(f"Conflict {conflict_id} resolved with outcome: {outcome}")

import os
from dotenv import load_dotenv

def main():
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN not found in .env file.")
        return
    try:
        bot.run(token)
    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
