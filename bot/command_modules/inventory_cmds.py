# bot/command_modules/inventory_cmds.py
import discord
from discord import slash_command
from typing import Optional
# from bot.bot_core import global_game_manager # if needed


TEST_GUILD_IDS = []

@slash_command(name="inventory", description="Показать содержимое инвентаря.", guild_ids=TEST_GUILD_IDS)
async def cmd_inventory(ctx: discord.ApplicationContext):
    await ctx.respond("**Мастер:** Инвентарь пока не реализован полностью.")

# Add /use, /drop, etc.