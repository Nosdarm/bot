import discord
from discord import app_commands, Interaction # Updated imports
from typing import TYPE_CHECKING, cast # Added cast

if TYPE_CHECKING:
    from bot.bot_core import RPGBot # Keep for type hinting client
# Actual import for runtime use with cast
from bot.bot_core import RPGBot


TEST_GUILD_IDS = [] # Add your test server ID(s) - this can be populated from settings or RPGBot

@app_commands.command(name="ping", description="Check if the bot is alive and its latency.")
async def cmd_ping(interaction: Interaction): # Changed ctx to interaction
    # Access bot instance via interaction.client
    # The client attribute of Interaction is the Bot instance.
    bot_instance = cast(RPGBot, interaction.client) # Used cast and direct type

    if bot_instance and hasattr(bot_instance, 'latency'):
         latency_ms = round(bot_instance.latency * 1000, 2)
         await interaction.response.send_message(f"Pong! Latency: {latency_ms}ms.", ephemeral=True)
    else:
        # Fallback if latency is not available or bot_instance is not as expected
        await interaction.response.send_message("Pong! (Could not retrieve bot latency.)", ephemeral=True)
