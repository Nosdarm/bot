import discord
from discord import slash_command # Or commands.Cog
from typing import Optional

# --- Temporary global references ---
from bot.bot_core import global_game_manager
# --- End temporary global references ---

TEST_GUILD_IDS = [] # Copy from bot_core.py


# Placeholder for /interact command
@slash_command(name="interact", description="Взаимодействовать с чем-то или кем-то.", guild_ids=TEST_GUILD_IDS)
async def cmd_interact(ctx: discord.ApplicationContext, target: str, action: str, *, details: Optional[str] = None):
    await ctx.defer()
    if global_game_manager:
         response_data = await global_game_manager.process_player_action(
             server_id=ctx.guild.id,
             discord_user_id=ctx.author.id,
             action_type="interact",
             action_data={"target": target, "action": action, "details": details}
         )
         await ctx.followup.send(response_data.get("message", "**Ошибка:** Неизвестный ответ от мастера."))
    else:
         await ctx.followup.send("**Ошибка Мастера:** Игровая система недоступна.")

# Placeholder for /attack command
@slash_command(name="attack", description="Атаковать цель.", guild_ids=TEST_GUILD_IDS)
async def cmd_attack(ctx: discord.ApplicationContext, target: str):
    await ctx.defer()
    if global_game_manager:
         response_data = await global_game_manager.process_player_action(
             server_id=ctx.guild.id,
             discord_user_id=ctx.author.id,
             action_type="attack",
             action_data={"target": target}
         )
         await ctx.followup.send(response_data.get("message", "**Ошибка:** Неизвестный ответ от мастера."))
    else:
         await ctx.followup.send("**Ошибка Мастера:** Игровая система недоступна.")

# Add other action commands here (/use, /talk, etc.)