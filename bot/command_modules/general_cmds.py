import discord
from discord import slash_command
from bot.bot_core import RPGBot # If using Bot methods

# --- ВРЕМЕННОЕ РЕШЕНИЕ для доступа бота ---
# NOT PRODUCTION READY
from bot.bot_core import get_bot_instance # Need a way to get bot instance for self.latency
# --- КОНЕЦ ВРЕМЕННОГО РЕШЕНИЯ ---

TEST_GUILD_IDS = [] # Add your test server ID(s)

@slash_command(name="ping", description="Проверить жив ли бот.", guild_ids=TEST_GUILD_IDS)
async def cmd_ping(ctx: discord.ApplicationContext):
    bot_instance = get_bot_instance() # Temporarily access bot instance
    if bot_instance:
         latency_ms = round(bot_instance.latency * 1000, 2)
         await ctx.respond(f"Понг! Задержка: {latency_ms} мс.")
    else:
        await ctx.respond("Понг! (Не удалось получить задержку бота.)")